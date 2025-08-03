#!/usr/bin/env python
import argparse
import torch
import torch.nn as nn
import torch.optim as optim
import torchvision
import torchvision.transforms as transforms

class ParamNet(nn.Module):
    def __init__(self, input_size, hidden_layers, output_size):
        super().__init__()
        layers = []
        prev = input_size
        for h in hidden_layers:
            layers.append(nn.Linear(prev, h))
            layers.append(nn.ReLU())
            prev = h
        layers.append(nn.Linear(prev, output_size))
        self.model = nn.Sequential(*layers)

    def forward(self, x):
        return self.model(x)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hidden', type=str, default="128", help="comma-separated hidden sizes, e.g. 256,128")
    parser.add_argument('--epochs', type=int, default=5, help="num epochs")
    parser.add_argument('--lr', type=float, default=0.001, help="learning rate")
    parser.add_argument('--batch_size', type=int, default=64, help="batch size")
    parser.add_argument('--save_model', type=str, default="model.pth", help="file to save model")
    parser.add_argument('--log_file', type=str, default="train.log", help="file to save logs")
    args = parser.parse_args()

    hidden_layers = [int(x) for x in args.hidden.split(",") if x.strip()]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.1307,), (0.3081,))
    ])
    trainset = torchvision.datasets.MNIST(root='./data', train=True, download=True, transform=transform)
    trainloader = torch.utils.data.DataLoader(trainset, batch_size=args.batch_size, shuffle=True)
    testset = torchvision.datasets.MNIST(root='./data', train=False, download=True, transform=transform)
    testloader = torch.utils.data.DataLoader(testset, batch_size=args.batch_size, shuffle=False)

    model = ParamNet(28*28, hidden_layers, 10).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=args.lr)

    with open(args.log_file, "w") as logf:
        for epoch in range(args.epochs):
            model.train()
            running_loss = 0.0
            for i, (inputs, labels) in enumerate(trainloader):
                inputs = inputs.view(-1, 28*28).to(device)
                labels = labels.to(device)
                optimizer.zero_grad()
                loss = criterion(model(inputs), labels)
                loss.backward()
                optimizer.step()
                running_loss += loss.item()
                if (i+1) % 100 == 0:
                    line = f"epoch {epoch+1}/{args.epochs} | batch {i+1} | loss {running_loss/100:.4f}\n"
                    print(line, end="", flush=True)
                    logf.write(line)
                    running_loss = 0.0

        model.eval()
        correct, total = 0, 0
        with torch.no_grad():
            for inputs, labels in testloader:
                inputs = inputs.view(-1, 28*28).to(device)
                labels = labels.to(device)
                outputs = model(inputs)
                _, predicted = torch.max(outputs, 1)
                total += labels.size(0)
                correct += (predicted == labels).sum().item()
        acc_line = f"test accuracy: {100*correct/total:.2f}%\n"
        print(line, end="", flush=True)
        logf.write(acc_line)

    torch.save(model.state_dict(), args.save_model)

if __name__ == "__main__":
    main()
